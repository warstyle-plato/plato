"""Занятость спрашивается прогоном один раз, дальше — только по требованию.

Владелец (01.09.2026): «так может один раз провести прогон как с моделью, а
потом только по требованию?».

Правило, из которого это следует: **занятость — ответ односторонний.** Отданная
площадка свободной не становится, значит спрашивать её второй раз незачем, а
поиск у нас платный. Поэтому прогон платит за площадку ровно один раз: строка
с ответом «занята» больше не спрашивается никогда, а неотвеченная и свободная
спрашиваются снова — там ответ ещё может измениться.

Второе, ради чего тест написан: разбор публикаций один на кнопку и на прогон.
Два разбора однажды ответили бы про одну площадку разное, и оба выглядели бы
верными — та же ошибка, что уже была у бота с сайтом и у отчёта с книгой.

Запуск: python3 -m pytest tests/test_occupancy_is_paid_for_once.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_ranking, ui  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")


def test_the_answer_survives_a_failed_recount():
    """Улика занятости — не результат счёта, и неудача модели её не стирает."""
    assert "press_facts" in krt_ranking._CATALOGUE_FIELDS, \
        "занятость не переживает неудавшийся пересчёт"
    previous = {"available": True, "slug": "site", "score": 70,
                "press_facts": {"available": True, "taken": True}}
    fresh = {"available": False, "slug": "site", "reason": "модель не посчиталась",
             "press_facts": {"available": True, "taken": True}}
    kept = krt_ranking.keep_computed(previous, fresh)
    assert kept["press_facts"]["taken"] is True
    assert kept["score"] == 70, "неудача затёрла посчитанное"


def test_the_row_carries_the_occupancy_from_the_run():
    row = krt_ranking.score_row(
        {"slug": "site", "name": "Площадка"},
        {"available": False, "reason": "нет модели",
         "press_facts": {"available": True, "taken": True, "agreement": [{"quote": "q"}]}},
    )
    assert row["press_facts"]["taken"] is True, \
        "прогон спросил источники, а в строку рейтинга ответ не попал"


def test_a_taken_site_is_never_asked_again():
    """Занятая площадка второй раз денег не стоит."""
    body = API[API.index("def _open_sources_for_run("):]
    body = body[:body.index("\n    def _screen_one(")]
    assert 'stored.get("taken")' in body, \
        "прогон переспрашивает занятую площадку — платит за уже полученный ответ"
    assert "return stored" in body, \
        "прежний ответ не возвращается, а значит теряется"


def test_an_unanswered_site_is_asked_again():
    body = API[API.index("def _open_sources_for_run("):]
    body = body[:body.index("\n    def _screen_one(")]
    assert "_read_open_sources(project)" in body, \
        "неотвеченная площадка не спрашивается вовсе — «не знаем» застынет навсегда"


def test_the_run_asks_the_same_reader_as_the_button():
    """Один разбор на обе двери."""
    assert API.count("def _read_open_sources(") == 1, \
        "разбор публикаций объявлен дважды — два ответа на один вопрос"
    route = API[API.index('/auctions/krt/{slug}/open-sources'):]
    route = route[:route.index('/auctions/krt/{slug}/card-facts')]
    assert "_read_open_sources" in route, "кнопка пошла своим путём мимо общего разбора"
    assert "read_findings" not in route, "у кнопки завёлся свой разбор"
    assert '_open_sources_for_run(project)' in API, "прогон источники не спрашивает вовсе"


def test_the_page_reads_the_occupancy_stored_by_the_run():
    page = ui.auctions_page(None)
    assert re.search(r"state\.krtPress\[x\.slug\]\|\|rank\.press_facts", page), \
        "экран видит занятость только после нажатия кнопки, хотя прогон её уже записал"
