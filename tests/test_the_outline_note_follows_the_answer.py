"""Чем очерчена площадка — ответ маршрута, а не постоянная строка.

Карточка КРТ печатала «Официальный полигон границ пока не получен. Анализ
использует геокодированную точку» у ВСЕХ площадок — и после того, как файл
карты реестра принёс контуры 247 площадок из 282. Оговорка объявляла
приближением ровно то, что приехало официальным полигоном.

Тот же класс, что «полигон границ каталогом не публикуется» в `/point`:
оговорка про источник обязана пережить смену источника.

Запуск: python3 -m pytest tests/test_the_outline_note_follows_the_answer.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402


def _page() -> str:
    return ui.auctions_page()


def _function(page: str, name: str) -> str:
    """Тело функции по скобкам: контракт — сама функция, а не соседняя строка."""
    start = page.index(f"function {name}(")
    depth, opened = 0, False
    for pos in range(start, len(page)):
        ch = page[pos]
        if ch == "{":
            depth, opened = depth + 1, True
        elif ch == "}":
            depth -= 1
            if opened and depth == 0:
                return page[start:pos + 1]
    raise AssertionError(f"функция {name} не закрыта")


def test_the_card_does_not_state_the_outline_is_missing() -> None:
    page = _page()
    assert "Официальный полигон границ пока не получен" not in page, (
        "оговорка стояла у всех площадок, включая те, у которых контур есть")


def test_the_note_names_every_answer_of_the_route() -> None:
    """У каждого ответа `/point` своя строка — включая «не спрашивали»."""
    body = _function(_page(), "krtOutlineNote")
    for status in ("official_polygon", "official_centre_only", "geocoded_point",
                   "not_published_in_catalogue"):
        assert status in body, f"ответ {status} на экране не назван"
    # «Не знаем» и «границ нет» — разные ответы, и умолчание говорит первое.
    assert "не спрошены" in body


def test_the_official_outline_is_not_called_an_approximation() -> None:
    body = _function(_page(), "krtOutlineNote")
    official = body[body.index("official_polygon"):body.index("official_centre_only")]
    assert "приближени" in official, "у официального контура сказано, что приближения нет"
    assert "notice'," in official.replace('"', "'"), "официальный контур не тревога"


def test_the_note_is_set_after_the_point_arrives() -> None:
    """Строку ставит ответ маршрута, а не разметка карточки."""
    body = _function(_page(), "loadKrtPoint")
    assert "krtOutlineNote(d.geometry_status)" in body
    # Не построилась карта — оговорка не остаётся обещанием «читаю файл».
    assert re.search(r"krtOutlineNote\(\s*''\s*\)", body)
