"""Публикации читаются отдельным дешёвым проходом по планируемым площадкам.

Владелец, 01.09.2026: «мне не надо в реализации, их в планируемых тоже можно
найти легко» и «всё легко находится тупо поиском в Яндекс Алиса». У планируемой
площадки карточка города застройщика не называет (0 из 30 измеренных) — ответ
есть только в публикациях. А поиск был заперт внутри полного прогона, который
на каждой площадке ещё строит рыночный отчёт и гоняет движок: минуты на
площадку, отсюда «раз в неделю».

Проход отвечает на один вопрос и стоит своих запросов. Уже спрошенные
пропускаются: занятая площадка свободной не станет.

Запуск: python3 -m pytest tests/test_the_press_pass_is_cheap_and_covers_the_planned.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
PAGE = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")


def _route() -> str:
    start = API.index('    @app.post("/auctions/krt/press/run")')
    return API[start:API.index("\n    def _stored_report", start)]


def test_the_pass_neither_models_nor_reads_the_market() -> None:
    """Дешёвый — значит без рынка и без движка, и это сказано вслух."""
    start = API.index("    def _press_only(")
    # Граница — следующее объявление, а не соседний маршрут: рядом с проходом
    # стоит выбор «чем считать строку», и он в этот кусок не входит.
    body = API[start:API.index("\n    def ", start + 1)]
    assert "_open_sources_for_run" in body
    for heavy in ("build_report", "_market_digest", "krt_registry.requirements"):
        assert heavy not in body, f"{heavy}: проход обязан оставаться дешёвым"
    assert "модель и рынок в нём не считаются" in body


def test_only_the_planned_are_asked() -> None:
    route = _route()
    assert "реализац" in route, "у площадки в реализации застройщика называет карточка"
    assert "taken" in route, "уже спрошенную и занятую второй раз не спрашиваем"


def test_one_reader_and_one_lock() -> None:
    """Второго разбора и второго замка не заводим."""
    route = _route()
    assert "krt_ranking.start" in route, "замок общий с прогоном модели"
    assert "_press_only" in route
    # Разбор публикаций объявлен один раз — его зовёт и кнопка карточки, и оба
    # прохода: два разбора однажды ответили бы про одну площадку разное.
    assert API.count("def _read_open_sources(") == 1


def test_the_page_asks_the_server_not_batches_of_its_own() -> None:
    assert "/auctions/krt/press/run" in PAGE
    assert "readKrtPressForFiltered" not in PAGE
    assert "KRT_PRESS_BATCH" not in PAGE, (
        "порции по 25 из браузера — это одиннадцать нажатий на каталоге из 263")
    assert "Прочитать публикации по планируемым" in PAGE
