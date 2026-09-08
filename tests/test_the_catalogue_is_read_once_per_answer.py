"""Список КРТ собирается по ОДНОМУ чтению каталога, а не по двум.

«Задвоились?» — владелец, 09.09.2026, экран `/auctions` в 00:46 МСК: плитка
показывала **796 проектов · схлопнуто 55 вторых публикаций**, при том что через
минуту оба воркера отдавали 530 и 37. Разложение сходится до строки: 796 = 282
карточки каталога + 514 решений, у которых карточку «не нашли», а 530 = те же
282 + 248. То есть в тот миг НИ ОДНО решение не сопоставилось с карточкой, и
каждая площадка, у которой карточка есть, встала в список дважды — строкой
каталога и строкой «проект решения, карточки нет».

Причина не в правиле сопоставления. Ответ маршрута собирался ДВУМЯ чтениями
снимка каталога: `/auctions/krt` читал его для строк, а `decisions()` читал его
заново для разложения — и между двумя чтениями фоновый обход подменял файл.
Замер прода того же часа (обход вызван кнопкой, ответы сняты подряд):

    строк 530 | каталог 102 | решений 428 | вторых 55 | complete False
    строк 522 | каталог  84 | решений 438 | вторых 55 | complete False
    строк 532 | каталог 272 | решений 260 | вторых 40 | complete False

— каталог посреди обхода падает с 282 строк до 84, а «решений без карточки»
ровно на столько же прибывает. Правило то же, что у балла площадки: одна
функция ещё не значит один ответ — ответ один, когда один вход.

Отсюда две правки и три проверки ниже: разложение считается по тому списку,
который вызывающий уже прочитал, а недособранный обход не затирает прежний
полный снимок — иначе наш пробел чтения показывается ответом источника.

Запуск: python3 -m pytest tests/test_the_catalogue_is_read_once_per_answer.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import KrtRegistry  # noqa: E402

# Одна площадка города: карточка в каталоге и проект решения о ней же.
CARD = {"slug": "kotlyakovo-1", "okrug": "ЮАО", "area_ha": 10.33,
        "name": "в производственной зоне № 32 «Котляково» (территория № 1)"}
DECISION = {"id": "266482220",
            "url": "https://www.mos.ru/dgi/documents/view/266482220/",
            "title": "Проект решения о КРТ",
            "address": "в производственной зоне № 32 «Котляково» (территория № 1)",
            "published_at": 1644993344, "department": "ДГИ"}


def _registry(tmp_path, catalogue_calls: list[int]) -> KrtRegistry:
    """Реестр, у которого снимок каталога МЕНЯЕТСЯ между чтениями.

    Так ведёт себя файл под фоновым обходом: первое чтение застаёт прежний
    полный снимок, второе — страницу, прочитанную обходом к этой секунде.
    """
    registry = KrtRegistry(tmp_path, fetch=lambda url: b"")
    answers = [[dict(CARD)], []]

    def catalogue(**_):
        catalogue_calls.append(1)
        return answers[min(len(catalogue_calls) - 1, len(answers) - 1)]

    registry.catalogue = catalogue  # type: ignore[assignment]
    path = registry.decisions_path
    path.parent.mkdir(parents=True, exist_ok=True)
    from market_search.krt_registry import DECISIONS_CACHE_SCHEMA_VERSION
    import time
    path.write_text(json.dumps({
        "schema_version": DECISIONS_CACHE_SCHEMA_VERSION,
        "retrieved_at": int(time.time()), "complete": True, "stale": False,
        "all": [DECISION], "query": "",
    }), encoding="utf-8")
    return registry


def test_the_split_uses_the_list_it_was_given(tmp_path) -> None:
    """Переданный каталог и есть тот, с которым сверяются, — снимок не читается."""
    calls: list[int] = []
    registry = _registry(tmp_path, calls)
    found = registry.decisions(catalogue=[dict(CARD)])
    assert not calls, "разложение полезло читать снимок заново"
    assert found["matched"] == 1, "площадка не узнала свою карточку"
    assert found["decisions"] == [], "площадка с карточкой встала строкой «без карточки»"


def test_a_second_read_of_the_snapshot_doubles_the_site(tmp_path) -> None:
    """Здесь и живёт задвоение: без переданного списка второе чтение уже пусто."""
    calls: list[int] = []
    registry = _registry(tmp_path, calls)
    assert registry.decisions()["matched"] == 1, "первое чтение и должно совпасть"
    # Второе чтение застаёт снимок подменённым — площадка «теряет» карточку.
    assert registry.decisions()["matched"] == 0
    assert len(registry.decisions()["decisions"]) == 1


def test_the_route_passes_its_own_read() -> None:
    """Маршрут обязан отдать разложению ТОТ ЖЕ список, по которому строит строки.

    Проверка гоняет настоящий маршрут: у поддельного реестра снимок каталога
    меняется от чтения к чтению, как под обходом. Пока маршрут читал дважды,
    в ответе стояли две строки об одной площадке — карточка и «карточки нет».
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import auction_search.api as auction_api

    reads: list[int] = []
    answers = [[dict(CARD)], []]

    def catalogue(**_):
        reads.append(1)
        return answers[min(len(reads) - 1, len(answers) - 1)]

    def decisions(*, catalogue=None, **_):
        # Поддельное разложение ведёт себя как настоящее: не дали список —
        # читает снимок сам.
        seen = catalogue if catalogue is not None else globals()["_CATALOGUE"]()
        matched = any(str(one.get("slug")) == CARD["slug"] for one in seen)
        return {"decisions": [] if matched else [DECISION],
                "matched_rows": [], "tep": {}, "complete": True, "matched": int(matched)}

    globals()["_CATALOGUE"] = catalogue
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=catalogue,
            status=lambda: {"complete": True, "refreshing": False},
            decisions=decisions,
        ),
    )
    auction_api.install(app)
    payload = TestClient(app).get("/auctions/krt").json()
    names = [str(row.get("name") or "") for row in payload["projects"]]
    assert len(names) == len(set(names)), f"площадка встала в список дважды: {names}"
    assert payload["count"] == 1 and payload["no_card_count"] == 0


def test_an_unfinished_crawl_keeps_the_complete_snapshot(tmp_path) -> None:
    """Недособранный обход прежний полный снимок не затирает.

    Иначе каталог на экране падает с 282 строк до 84 — и площадки, чьи карточки
    ещё не дочитаны, показываются как «карточки нет», то есть наш пробел чтения
    выдаётся за ответ города.
    """
    whole = ('<a href="/projects/alpha/">Альфа</a><span>Площадь: 10</span>'
             '<a href="/projects/beta/">Бета</a><span>Площадь: 20</span>')
    page_one = ('<a href="/projects/alpha/">Альфа</a><span>Площадь: 10</span>'
                '<a class="show_more" data-url="/projects/?page=2">ещё</a>')

    # Сначала обход доходит до конца: город больше не обещает «показать ещё».
    registry = KrtRegistry(tmp_path, fetch=lambda url: whole.encode("utf-8"))
    full = registry.projects(refresh=True)
    before = json.loads(registry.path.read_text(encoding="utf-8"))
    assert before["complete"] is True and len(before["projects"]) == len(full) == 2

    # А теперь обход обрывается на второй странице — и оба пути падают.
    def truncated(url: str) -> bytes:
        if "page=2" in url or "r.jina.ai" in url:
            raise OSError("источник оборвался посреди обхода")
        return page_one.encode("utf-8")

    registry.fetch = truncated  # type: ignore[assignment]
    registry.projects(refresh=True)
    after = json.loads(registry.path.read_text(encoding="utf-8"))
    assert after["complete"] is True, "усечённый обход объявил снимок неполным"
    assert after["projects"] == before["projects"], "усечённый обход затёр полный снимок"


def test_the_first_ever_crawl_still_shows_what_it_read(tmp_path) -> None:
    """А там, где полного снимка нет вовсе, неполный лучше пустоты — и назван.

    Без этого первый в жизни обход оставлял бы экран пустым до самого конца, а
    «пусто» читается как «в реестре ничего нет».
    """
    page_one = ('<a href="/projects/alpha/">Альфа</a><span>Площадь: 10</span>'
                '<a class="show_more" data-url="/projects/?page=2">ещё</a>')

    def fetch(url: str) -> bytes:
        if "page=2" in url or "r.jina.ai" in url:
            raise OSError("источник оборвался посреди первого обхода")
        return page_one.encode("utf-8")

    registry = KrtRegistry(tmp_path, fetch=fetch)
    registry.projects(refresh=True)
    saved = json.loads(registry.path.read_text(encoding="utf-8"))
    assert len(saved["projects"]) == 1
    assert saved["complete"] is False, "усечённый список объявлен полным"
