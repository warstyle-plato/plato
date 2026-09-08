"""Куски скрипта страницы для стендов на node — по границам, а не перечислением.

Стенд, который собирает скрипт из функций ПО ИМЕНАМ, падает на правке страницы,
а не на том, что он проверяет: рядом появилась функция — «X is not defined», и
разбирать приходится чужое падение вместо своего. Так уже было с
`parkingRequirement`, и 07.09.2026 повторилось с `applyDerivedInputs`: замок
«Требования КРТ» встал на пути выгрузки ГлавАПУ, и три стенда упали разом,
ничего не сказав о том, что сломалось на самом деле (ничего).

Границей куска служат скобки и собственное объявление, а не соседняя строка, и
ответ на «где живёт этот кусок» один на все стенды: две копии разошлись бы
молча — так же молча, как расходятся две копии любого другого правила.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def function(name: str, page: str | None = None) -> str:
    """Тело функции страницы целиком, по балансу скобок.

    Страница по умолчанию основная (`PAGE`); у торгов своя, и берётся она тем
    же способом — иначе у одного правила «где живёт этот кусок» завелось бы
    два ответа.
    """
    page = core.PAGE if page is None else page
    declaration = f"function {name}("
    start = page.find(declaration)
    if start < 0:
        raise AssertionError(f"на странице нет функции {name}")
    depth = 0
    for position in range(page.index("{", start), len(page)):
        if page[position] == "{":
            depth += 1
        elif page[position] == "}":
            depth -= 1
            if depth == 0:
                return page[start:position + 1]
    raise AssertionError(f"тело функции {name} не закрыто скобкой")


def krt_lock() -> str:
    """Замок «Требования КРТ» со списком запертых полей и общим писателем.

    Через `applyDerivedInputs` пишут вводные и пересчёт ТЭП, и выгрузка
    ГлавАПУ: приоритет по полю не зависит от того, кто пишет.
    """
    page = core.PAGE
    start = page.find("const KRT_REQUIREMENT_INPUTS=")
    if start < 0:
        raise AssertionError("на странице нет списка запертых требованием КРТ полей")
    end = page.find("function applyDerivedInputs(", start)
    if end < 0:
        raise AssertionError("на странице нет общего писателя вводных applyDerivedInputs")
    return page[start:end] + function("applyDerivedInputs")


def auctions_function(*names: str) -> str:
    """Те же куски, но со страницы торгов (`auction_search.ui`).

    Страница там собирается плейсхолдерами, поэтому берётся СОБРАННАЯ: в сырой
    константе на месте кусков стоят метки, и стенд падал бы первой же строкой.
    """
    from auction_search import ui  # локально: движок тянуть незачем

    page = ui.auctions_page()
    return "\n".join(function(name, page) for name in names)
