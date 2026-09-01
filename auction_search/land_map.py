"""Живая карта — одна на весь сервис, и страница торгов берёт её, а не пишет свою.

Карта КРТ рисовалась одной серверной склейкой `/land/basemap`: картинка, у
которой нет ни увеличения, ни перетаскивания (владелец, 01.09.2026: «карта у
нас нормальная теперь или такая же статичная?» — такая же). Тайловая карта у
сервиса при этом есть давно: она живёт в `PAGE`, считает проекцию одной
функцией на тайлы, контур и линейку, и знает, что меркаторный метр не метр
земли.

Скопировать её сюда было нельзя по той же причине, по которой нет копии
`VERSION`: копию негде обновлять, а разошедшиеся проекции кладут контур рядом с
подложкой — и выглядит это как неточность источника, а не как наша ошибка.
Поэтому код вынимается из `PAGE` по именам: **функция — контракт**, она либо
есть, либо её нет, и второе настоящая поломка. Границей служат скобки, а не
соседняя строка: сосед переписывается вместе с чужой правкой, и проверка тогда
падает, ничего не сказав о том, что сломалось.

Запуск проверки: python3 -m pytest tests/test_the_krt_map_is_the_engine_map.py -q
"""

from __future__ import annotations

import re

PLACEHOLDER = "__DEVELOPAID_LAND_MAP_KIT__"
MARKUP_PLACEHOLDER = "__DEVELOPAID_LAND_MAP_DIALOG__"

# Что вынимается. Порядок не важен — это объявления функций.
FUNCTIONS = (
    "landMapScale", "landMapLat", "landMapWorldPx", "landMapWorldPy",
    "landMapProject", "landMapUnproject", "landMapView",
    "landMapGround", "landMapMetres",
    "openLandMap", "closeLandMap", "landMapZoomBy", "landMapMeasureToggle",
    "landMapPoint", "landMapClick", "landMapDown", "landMapMove", "landMapUp",
    "landMapWheel", "renderLandMap",
    # Помощники, которыми карта пользуется. Своих на странице торгов нет, а
    # завести вторые значило бы получить два разных округления одного числа.
    "landNum", "escapeHtml",
)

# Константы мира: те же числа, что у серверной склейки.
CONSTANTS = ("LAND_MAP_WORLD", "LAND_MAP_ORIGIN")

_DIALOG_START = '<div id="landMapDialog"'


class MissingPiece(RuntimeError):
    """Куска карты в `PAGE` нет. Это поломка, а не повод нарисовать своё."""


def _function(page: str, name: str) -> str:
    """Тело функции по имени. Граница — скобки, а не соседняя строка."""
    match = re.search(r"^function\s+" + re.escape(name) + r"\s*\(", page, re.M)
    if not match:
        raise MissingPiece(f"в PAGE нет функции {name}")
    start = match.start()
    depth, seen, index = 0, False, page.index("{", match.end() - 1)
    while index < len(page):
        char = page[index]
        if char == "{":
            depth, seen = depth + 1, True
        elif char == "}":
            depth -= 1
            if seen and depth == 0:
                return page[start:index + 1]
        index += 1
    raise MissingPiece(f"у функции {name} не нашёлся конец")


def _constant(page: str, name: str) -> str:
    match = re.search(r"^const\s+" + re.escape(name) + r"\s*=.*?;", page, re.M | re.S)
    if not match:
        raise MissingPiece(f"в PAGE нет константы {name}")
    return match.group(0)


def dialog_markup(page: str) -> str:
    """Разметка окна карты — оттуда же, где живёт её код."""
    start = page.find(_DIALOG_START)
    if start < 0:
        raise MissingPiece("в PAGE нет окна карты")
    depth, index = 0, start
    while index < len(page):
        if page.startswith("<div", index):
            depth += 1
        elif page.startswith("</div>", index):
            depth -= 1
            if depth == 0:
                return page[start:index + len("</div>")]
        index += 1
    raise MissingPiece("у окна карты не нашёлся конец")


def script(core) -> str:
    """Код живой карты для чужой страницы. Нет движка — пустая строка.

    Пусто здесь значит «карта не подключена», и страница говорит это вслух:
    молча отсутствующая кнопка неотличима от сломанной.
    """
    page = getattr(core, "PAGE", "") if core is not None else ""
    if not page:
        return ""
    parts = ["let LAND_MAP=null;"]
    parts += [_constant(page, name) for name in CONSTANTS]
    parts += [_function(page, name) for name in FUNCTIONS]
    return "\n".join(parts)


def markup(core) -> str:
    page = getattr(core, "PAGE", "") if core is not None else ""
    return dialog_markup(page) if page else ""
